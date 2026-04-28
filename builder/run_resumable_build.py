from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "builder" / "output"
STATE_DIR = PROJECT_ROOT / "builder" / ".state"
STATE_FILE = STATE_DIR / "build_resume_state.json"

STAGES = {
    1: {
        "name": "stage_dist_stage_packages_updates",
        "description": "Build or reuse dist and regenerate stage/packages/updates without ISCC",
        "args": ["build.py", "--skip-installer-compile"],
    },
    2: {
        "name": "stage_installer_compile",
        "description": "Compile installer from staged outputs",
        "args": ["build.py", "--skip-pyinstaller"],
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict[str, object]:
    if not STATE_FILE.exists():
        return {
            "schema": 1,
            "updated_at_utc": "",
            "last_success_stage": 0,
            "history": [],
        }
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state must be an object")
        data.setdefault("schema", 1)
        data.setdefault("updated_at_utc", "")
        data.setdefault("last_success_stage", 0)
        data.setdefault("history", [])
        return data
    except Exception:
        return {
            "schema": 1,
            "updated_at_utc": "",
            "last_success_stage": 0,
            "history": [],
        }


def _save_state(state: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at_utc"] = _utc_now()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_history(state: dict[str, object], item: dict[str, object]) -> None:
    history = state.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        state["history"] = history
    history.append(item)
    if len(history) > 50:
        del history[:-50]


def _run_stage(
    stage_no: int,
    python_exe: str,
    env: dict[str, str],
    state: dict[str, object],
    args_override: list[str] | None = None,
) -> None:
    stage = STAGES[stage_no]
    stage_args = args_override if args_override is not None else list(stage["args"])
    cmd = [python_exe, *stage_args]
    print("\n" + "=" * 78)
    print(f"Running stage {stage_no}: {stage['name']}")
    print(f"Description: {stage['description']}")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 78)

    start = _utc_now()
    try:
        completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, check=False)
    except KeyboardInterrupt:
        end = _utc_now()
        _append_history(
            state,
            {
                "stage": stage_no,
                "name": stage["name"],
                "started_at_utc": start,
                "ended_at_utc": end,
                "command": cmd,
                "return_code": None,
                "status": "interrupted",
            },
        )
        _save_state(state)
        raise
    end = _utc_now()

    history_item = {
        "stage": stage_no,
        "name": stage["name"],
        "started_at_utc": start,
        "ended_at_utc": end,
        "command": cmd,
        "return_code": completed.returncode,
    }

    if completed.returncode == 0:
        state["last_success_stage"] = max(int(state.get("last_success_stage", 0)), stage_no)
        _append_history(state, {**history_item, "status": "success"})
        _save_state(state)
        print(f"[OK] Stage {stage_no} succeeded")
        return

    _append_history(state, {**history_item, "status": "failed"})
    _save_state(state)
    raise SystemExit(
        f"Stage {stage_no} failed with exit code {completed.returncode}. "
        f"Resume with: {python_exe} builder/run_resumable_build.py --from-stage {stage_no}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PyInstaller release build in resumable stages.",
    )
    parser.add_argument(
        "--from-stage",
        type=int,
        choices=sorted(STAGES.keys()),
        help="Start from this stage number instead of state-based auto-resume.",
    )
    parser.add_argument(
        "--clean-state",
        action="store_true",
        help="Reset resume state before execution.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current resume state and exit.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to run build commands with (default: current interpreter).",
    )
    parser.add_argument(
        "--only-stage",
        type=int,
        choices=sorted(STAGES.keys()),
        help="Run only one specific stage and exit.",
    )
    parser.add_argument(
        "--reuse-dist",
        action="store_true",
        help=(
            "For stage 1, reuse existing builder/output/dist/AIPacs instead of rerunning "
            "PyInstaller (equivalent to adding --skip-pyinstaller)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = _load_state()

    if args.clean_state:
        state = {
            "schema": 1,
            "updated_at_utc": "",
            "last_success_stage": 0,
            "history": [],
        }
        _save_state(state)

    if args.status:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    env = os.environ.copy()
    env.setdefault("AIPACS_ALLOW_MISSING_ADVANCED_MPR", "1")
    env.setdefault("PYTHONUTF8", "1")

    if args.only_stage:
        stages_to_run = [args.only_stage]
    elif args.from_stage:
        stages_to_run = [s for s in sorted(STAGES.keys()) if s >= args.from_stage]
    else:
        next_stage = int(state.get("last_success_stage", 0)) + 1
        if next_stage > max(STAGES.keys()):
            print("All stages already completed. Use --from-stage to rerun specific stages.")
            return 0
        stages_to_run = [s for s in sorted(STAGES.keys()) if s >= next_stage]

    print(f"Resume state file: {STATE_FILE}")
    print(f"Running stages: {stages_to_run}")

    for stage_no in stages_to_run:
        stage_args_override: list[str] | None = None
        if stage_no == 1 and args.reuse_dist:
            stage_args_override = ["build.py", "--skip-pyinstaller", "--skip-installer-compile"]
        _run_stage(stage_no, args.python, env, state, stage_args_override)

    print("\n[OK] Resumable build flow completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
