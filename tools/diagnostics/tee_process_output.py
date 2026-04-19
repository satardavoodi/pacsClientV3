from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a process and tee combined stdout/stderr to a UTF-8 log file."
    )
    parser.add_argument("--cwd", required=True, help="Working directory for the child process")
    parser.add_argument("--log-file", required=True, help="Path to the UTF-8 log file")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.command:
        print("[tee_process_output] No command provided", file=sys.stderr)
        return 2

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("[tee_process_output] No command provided after '--'", file=sys.stderr)
        return 2

    cwd = Path(args.cwd)
    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("w", encoding="utf-8", newline="") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line)
            log_file.flush()

        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())