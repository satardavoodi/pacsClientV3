from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> int:
    script = PROJECT_ROOT / "builder" / "build_release.py"
    # -u (unbuffered): build_release.py's own print() output is block-buffered
    # when stdout is redirected to a log, while its SUBPROCESS output (PyInstaller,
    # ISCC) streams straight through the inherited handle. The result was a log
    # that interleaved out of order and, worse, RELEASE_GATE verdicts that did not
    # appear until the process exited — so a ~50-minute build gave no live signal
    # about whether its gates had passed. Unbuffering costs nothing and makes the
    # gate lines visible the moment they are printed.
    args = [sys.executable, "-u", str(script), *sys.argv[1:]]
    return subprocess.call(args, cwd=str(PROJECT_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
